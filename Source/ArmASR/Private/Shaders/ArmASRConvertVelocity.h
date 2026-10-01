// This file is part of the FidelityFX Super Resolution 2.2 Unreal Engine Plugin.
//
// Copyright (c) 2022-2023 Advanced Micro Devices, Inc. All rights reserved.
// Copyright © 2024-2025 Arm Limited.
// SPDX-License-Identifier: MIT
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.

#include "GlobalShader.h"
#include "RenderGraphFwd.h"
#include "ShaderCompilerCore.h"
#include "ShaderParameterStruct.h"
#include "SceneTextureParameters.h"

class FArmASR_CopyInputs : SHADER_PERMUTATION_BOOL("ARMASR_COPY_INPUTS");

// Motion source, see ConvertVelocity.usf: 0 UE scene velocity, 1 AppSpaceWarp motion vectors, 2 depth only,
// 3 raw (unencoded, float) scene velocity written by the SpaceWarp velocity shaders.
enum class EArmASRVelocitySource : int32
{
	SceneVelocity = 0,
	SpaceWarp = 1,
	DepthOnly = 2,
	SceneVelocityRaw = 3,
	MAX
};
class FArmASR_VelocitySource : SHADER_PERMUTATION_ENUM_CLASS("ARMASR_VELOCITY_SOURCE", EArmASRVelocitySource);

class FArmASRConvertVelocity : public FGlobalShader
{
public:
	DECLARE_GLOBAL_SHADER(FArmASRConvertVelocity);
	SHADER_USE_PARAMETER_STRUCT(FArmASRConvertVelocity, FGlobalShader);

	using FPermutationDomain = TShaderPermutationDomain<FArmASR_CopyInputs, FArmASR_VelocitySource>;

	BEGIN_SHADER_PARAMETER_STRUCT(FParameters, )
		SHADER_PARAMETER_RDG_TEXTURE_SRV(Texture2D, InputDepth)
		SHADER_PARAMETER_RDG_TEXTURE_SRV(Texture2D, InputVelocity)
		SHADER_PARAMETER_RDG_TEXTURE_SRV(Texture2D, InputMotionVector)
		SHADER_PARAMETER_SAMPLER(SamplerState, InputMotionVectorSampler)
		SHADER_PARAMETER_RDG_TEXTURE_SRV(Texture2D, InputColor)
		SHADER_PARAMETER(FIntPoint, InputOffset)
		SHADER_PARAMETER_STRUCT_REF(FViewUniformShaderParameters, View)
		RENDER_TARGET_BINDING_SLOTS()
	END_SHADER_PARAMETER_STRUCT()

	static bool ShouldCompilePermutation(const FGlobalShaderPermutationParameters& Parameters)
	{
		// AppSpaceWarp motion vectors only exist on Vulkan mobile with vr.SupportMobileSpaceWarp.
		const FPermutationDomain PermutationVector(Parameters.PermutationId);
		if (PermutationVector.Get<FArmASR_VelocitySource>() != EArmASRVelocitySource::SceneVelocity && !IsMobilePlatform(Parameters.Platform))
		{
			return false;
		}
		return FArmASRGlobalShader::ShouldCompilePermutation(Parameters);
	}
	static void ModifyCompilationEnvironment(const FGlobalShaderPermutationParameters& Parameters, FShaderCompilerEnvironment& OutEnvironment)
	{
	}
};
